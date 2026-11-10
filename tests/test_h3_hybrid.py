"""H3: hybrid integration, acceptance cases CA-01..CA-08, causality and edge cases."""
import json
import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from ares.api import Session, handle_json  # noqa: E402
from ares.mission import HybridMission, validate_config  # noqa: E402


def first_move_mission(**kw):
    mission = HybridMission(seed=42, **kw)
    mission.step()
    return mission


# ------------------------------------------------------------------ CA-01
def test_ca01_mars_reproducible_at_least_ten_steps_consistent_telemetry():
    mission = HybridMission(planet='Marte', seed=42)
    records = [mission.step() for _ in range(12)]
    assert [r['step'] for r in records] == list(range(1, 13))
    for prev, cur in zip(records, records[1:]):
        assert 0 <= cur['battery'] <= 100
        for a, b in zip([prev['position']] + cur['moved'], cur['moved']):
            assert abs(a[0] - b[0]) + abs(a[1] - b[1]) == 1  # contiguous moves only
    assert len(mission.path) > 10


def test_same_seed_and_configuration_gives_identical_trace():
    a = HybridMission(seed=7).run()
    b = HybridMission(seed=7).run()
    ta = HybridMission(seed=7)
    tb = HybridMission(seed=7)
    ta.run(), tb.run()
    assert a['steps'] == b['steps']
    assert json.dumps(ta.logger.trace, sort_keys=True) == json.dumps(tb.logger.trace, sort_keys=True)


# ------------------------------------------------------------------ CA-02
def test_ca02_cliff_in_front_stops_before_danger_and_replans():
    mission = first_move_mission()
    runs_before = len(mission.ga_runs)
    entry = mission.inject('barranco')
    cliff = tuple(entry['position'])
    record = mission.step()
    assert record['reason'] == 'R04_VETO_BARRANCO_CONFIRMADO'
    assert tuple(record['position']) != cliff
    assert record['rna'] is not None and 'barranco' in record['rna']['probabilities']
    assert record['fuzzy']['rules'], 'fuzzy rules must be visible'
    assert len(mission.ga_runs) == runs_before + 1
    assert cliff not in [tuple(c) for c in mission.route]
    mission.run()
    assert cliff not in mission.path
    assert mission.metrics['safety_violations'] == 0


# ------------------------------------------------------------------ CA-03
def test_ca03_low_battery_prioritizes_refuge_or_explains():
    mission = HybridMission(seed=42, battery=12)
    mission.run()
    reasons = {r['reason'] for r in mission.logger.trace}
    assert mission.finished
    assert min(r['battery'] for r in mission.logger.trace) >= 0
    assert reasons & {'R07_RETORNO_ENERGIA', 'R06_REFUGIO_INALCANZABLE', 'R15_MISION_COMPLETA'}
    assert mission.metrics['safety_violations'] == 0


def test_battery_one_percent_far_refuge_declared_unreachable():
    mission = HybridMission(seed=42, battery=100)
    for _ in range(12):
        mission.step()
    mission.battery = 1.
    record = mission.step()
    assert record['reason'] in ('R06_REFUGIO_INALCANZABLE', 'R07_RETORNO_ENERGIA', 'R09_RECARGA', 'R15_MISION_COMPLETA')
    if record['reason'] == 'R06_REFUGIO_INALCANZABLE':
        assert mission.finished and mission.state == 'MODO_SEGURO'


def test_battery_zero_never_moves_and_never_negative():
    mission = HybridMission(seed=3, battery=0)
    record = mission.step()
    assert record['moved'] == [] and record['battery'] == 0
    assert mission.state == 'FRACASO'


# ------------------------------------------------------------------ CA-04
def test_ca04_generation_five_shows_three_chromosomes_and_operators():
    session = Session(seed=42)
    session.dispatch('step', {'n': 1})
    out = session.dispatch('ga_generation', {'generation': 5, 'run': 0})
    assert 'error' not in out
    assert len(out['rows']) >= 3
    assert all('fitness' in row for row in out['rows'])
    assert out['crossovers'] + out['mutations'] > 0


# ------------------------------------------------------------------ CA-05
def test_ca05_distance_10_to_1_changes_fuzzy_output():
    session = Session()
    far = session.dispatch('fuzzy_eval', {'distance': 10, 'battery': 60, 'slope': 5})
    near = session.dispatch('fuzzy_eval', {'distance': 1, 'battery': 60, 'slope': 5})
    assert near['speed'] < far['speed']
    assert {r['id'] for r in near['rules']} != {r['id'] for r in far['rules']}
    assert near['degrees']['distance']['cerca'] == 1.0


# ------------------------------------------------------------------ CA-06
def test_ca06_changing_rna_features_updates_probabilities():
    session = Session()
    base = dict(distance=10, slope=2, elevation_delta=0, texture=.25, visibility=1, vibration=0)
    free = session.dispatch('rna_eval', base)
    drop = session.dispatch('rna_eval', dict(base, distance=.05, elevation_delta=-10, slope=30, vibration=1.5))
    assert free['label'] == 'libre'
    assert drop['probabilities']['barranco'] > free['probabilities']['barranco']
    state = session.dispatch('state')
    assert 0 <= state['nn']['test']['barranco_recall'] <= 1
    assert state['nn']['test']['confusion_matrix']


# ------------------------------------------------------------------ CA-07
def test_ca07_jupiter_wheels_blocked_with_explanation():
    session = Session()
    out = session.dispatch('configure', {'planet': 'Júpiter', 'mode': 'rover'})
    assert 'error' in out and 'sonda' in out['error']
    ok = session.dispatch('configure', {'planet': 'Júpiter', 'mode': 'sonda'})
    assert ok['planet']['mode'] == 'probe'
    session.dispatch('step', {'n': 5})


# ------------------------------------------------------------------ CA-08
def test_ca08_same_seed_full_vs_ablation_and_export():
    session = Session(seed=11)
    out = session.dispatch('compare', {'seeds': 2, 'scenario': 'eventos', 'policies': ['hibrido', 'sin_rna']})
    assert {row['policy'] for row in out['summary']} == {'hibrido', 'sin_rna'}
    for row in out['summary']:
        assert set(row['success']) == {'media', 'mediana', 'desv'}
    session.dispatch('step', {'n': 5})
    csv_text = session.dispatch('export', {'format': 'csv'})['content']
    assert csv_text.count('\n') >= 6
    exported = json.loads(session.dispatch('export', {'format': 'json'})['content'])
    assert exported['config']['seed'] == 11 and len(exported['trace']) == 5


# -------------------------------------------------------------- causality
def test_causality_rna_output_changes_decision(monkeypatch):
    normal = first_move_mission()
    assert normal.step()['reason'] == 'R14_AVANCE'
    forced = first_move_mission()
    real_predict = forced.perception.predict

    def fake(features):
        out = real_predict(features)
        out.update(label='barranco', confidence=.95, probabilities={'libre': .02, 'obstaculo': .03, 'barranco': .95})
        return out
    monkeypatch.setattr(forced.perception, 'predict', fake)
    assert forced.step()['reason'] == 'R05_RNA_PELIGRO'


def test_causality_fuzzy_output_changes_movement(monkeypatch):
    normal = first_move_mission()
    assert normal.step()['moved']
    forced = first_move_mission()
    real_infer = forced.fuzzy.infer
    monkeypatch.setattr(forced.fuzzy, 'infer', lambda *a: {**real_infer(*a), 'speed': .02})
    record = forced.step()
    assert record['reason'] == 'R12_DIFUSO_PARAR' and record['moved'] == []


def test_causality_ga_output_changes_route():
    default = HybridMission(seed=42)
    default.step()
    no_science = HybridMission(seed=42, weights={'science': 0, 'distance': 1, 'energy': 1, 'predicted_risk': 2, 'time': 1})
    no_science.step()
    assert default.planned_history[0] != no_science.planned_history[0]


# ---------------------------------------------------------------- edges
@pytest.mark.parametrize('bad', [{'battery': math.nan}, {'battery': 150}, {'seed': -1}, {'policy': 'magia'},
                                 {'weights': {'science': math.inf}}])
def test_impossible_configuration_rejected_with_readable_message(bad):
    with pytest.raises(ValueError):
        validate_config(bad)
    assert 'error' in json.loads(handle_json(Session(), 'configure', json.dumps(bad).replace('NaN', '"NaN"')))


def test_all_navigation_sensors_failing_never_moves_blind():
    mission = first_move_mission()
    position = mission.position
    mission.inject('falla_sensor', sensor='todos')
    record = mission.step()
    assert record['reason'] == 'R02_SENSORES_NAVEGACION_FALLIDOS'
    assert tuple(record['position']) == position


def test_single_sensor_failure_degrades_without_exception():
    mission = first_move_mission()
    mission.inject('falla_sensor', sensor='distance')
    record = mission.step()
    assert record['reason'] in ('R13_AVANCE_DEGRADADO', 'R12_DIFUSO_PARAR', 'R11_REPLANIFICAR')
    assert record['rna'] is None and record['rna_error']


def test_simultaneous_meteorite_and_low_battery_resolved_deterministically():
    outcomes = []
    for _ in range(2):
        mission = first_move_mission()
        mission.inject('meteorito')
        mission.inject('bateria_baja')
        outcomes.append([mission.step()['reason'] for _ in range(4)])
    assert outcomes[0] == outcomes[1]


def test_map_without_science_sites_closes_without_division_by_zero():
    mission = HybridMission(seed=5, science_count=0)
    summary = mission.run()
    assert summary['science'] == 1.0 and mission.finished


def test_no_route_reports_no_solution():
    mission = HybridMission(seed=42)
    for cell in ((0, 1), (1, 0), (1, 1)):
        mission.world.obstacles.add(cell)
        mission.belief.obstacles.add(cell)
    mission.run()
    assert mission.finished
    assert any(r['reason'] == 'R10_SIN_RUTA' for r in mission.logger.trace)
    assert mission.metrics['distance'] == 0


def test_ga_route_crossing_confirmed_cliff_is_vetoed():
    mission = HybridMission(seed=42)
    accepted, rejected = mission.supervisor.filter_routes(
        [{'route': [(0, 0), (0, 1)], 'feasible': True}, {'route': [(0, 0), (1, 0)], 'feasible': True}],
        known_cliffs={(0, 1)}, known_obstacles=set())
    assert accepted == [1] and rejected[0]['reason'] == 'cruza peligro confirmado'


def test_events_cover_all_kinds_without_exception():
    for kind in ('bateria_baja', 'dia', 'noche', 'sismo', 'meteorito', 'tormenta_polvo', 'corrosion',
                 'biosenal_anomala', 'alienigena', 'falla_sensor', 'perdida_enlace', 'viento', 'barranco'):
        mission = first_move_mission()
        mission.inject(kind)
        mission.step()
        mission.step()


def test_biosignal_never_claims_life():
    mission = first_move_mission()
    entry = mission.inject('biosenal_anomala')
    assert 'no confirma vida' in entry['message']


# ------------------------------------------------- RF-11, RF-03, instruments
def test_initial_route_visible_before_first_step_and_after_reset():
    session = Session(seed=42)
    assert len(session.dispatch('state')['map']['route']) > 1
    session.dispatch('step', {'n': 6})
    snapshot = session.dispatch('reset')
    assert snapshot['status']['step'] == 0 and len(snapshot['map']['route']) > 1


def test_prepare_does_not_change_the_trace():
    plain, prepared = HybridMission(seed=9), HybridMission(seed=9).prepare()
    plain.run(), prepared.run()
    strip = lambda trace: [{k: v for k, v in row.items() if k != 'ga'} for row in trace]
    assert json.dumps(strip(plain.logger.trace), sort_keys=True) == json.dumps(strip(prepared.logger.trace), sort_keys=True)


def test_rf11_training_history_has_loss_and_accuracy_per_iteration():
    history = Session().dispatch('meta')['training']
    assert len(history) >= 10 and history[0]['iteration'] == 1
    assert history[-1]['loss'] < history[0]['loss']
    assert history[-1]['validation_accuracy'] > history[0]['validation_accuracy'] - 1e-9
    assert all(0 <= row['train_accuracy'] <= 1 for row in history)


def test_rf03_step_duration_scales_time_and_energy():
    short, long = HybridMission(seed=42, step_duration=1.), HybridMission(seed=42, step_duration=2.)
    a, b = short.step(), long.step()
    assert b['t'] == 2 * a['t']
    # Energy per cell scales with the step duration (routes may differ, so compare the cost model).
    assert long.cell_cost(.5, 3.) == pytest.approx(2 * short.cell_cost(.5, 3.))
    assert 'error' in Session().dispatch('configure', {'step_duration': 0})


def test_instruments_are_recovered_and_reported():
    mission = HybridMission(seed=42)
    summary = mission.run()
    assert summary['instruments_total'] == 3
    assert summary['instruments'] == 3 and summary['success']
    assert any(e['kind'] == 'instrumento' for e in mission.event_log)
    assert mission.recovered <= set(mission.path)


# --------------------------------------------- unconfirmed RNA beliefs
def test_probe_mission_recovers_from_false_rna_mark_blocking_the_refuge():
    mission = HybridMission(planet='Júpiter', mode='sonda', seed=21)
    summary = mission.run()
    assert summary['success'], summary['outcome']
    assert summary['safety_violations'] == 0


def test_unconfirmed_rna_marks_are_discarded_once_then_become_firm():
    mission = first_move_mission()
    row, col = mission.position
    ring = [(row + dr, col + dc) for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1))]
    ring = [c for c in ring if mission.world.traversable(c)]
    for cell in ring:
        mission._mark_rna(cell, 'obstaculo')
    mission._plan('PRUEBA')
    assert len(mission.route) > 1
    assert not mission.rna_marks and set(ring) <= mission.rna_retried
    assert not set(ring) & mission.belief.obstacles
    mission._mark_rna(ring[0], 'obstaculo')      # second independent RNA flag
    assert ring[0] in mission.belief.obstacles and ring[0] not in mission.rna_marks


def test_confirmed_hazards_are_never_discarded():
    mission = first_move_mission()
    entry = mission.inject('barranco')
    cliff = tuple(entry['position'])
    mission.step()                                # edge sensor confirms it
    mission._mark_rna((5, 5), 'obstaculo')
    mission.rna_marks.add((5, 5))
    for cell in list(mission.rna_marks):
        mission.belief.obstacles.discard(cell)
    mission._plan('PRUEBA')
    assert cliff in mission.belief.cliffs


# ------------------------------------------------------------ event guards
def test_hazard_event_never_defaults_onto_the_rover():
    for seed in range(12):
        mission = HybridMission(seed=seed).prepare()
        mission.step(), mission.step()
        try:
            entry = mission.inject('alienigena')
        except ValueError as error:
            assert 'adyacente' in str(error)       # only when no free neighbour exists
            continue
        assert tuple(entry['position']) != mission.position
        assert 'ficticio' in entry['message']


def test_events_are_rejected_after_the_mission_ends():
    mission = HybridMission(seed=42)
    mission.run()
    with pytest.raises(ValueError, match='ya terminó'):
        mission.inject('alienigena')


def test_alien_is_avoided_without_collision():
    mission = HybridMission(seed=42).prepare()
    mission.step(), mission.step()
    alien = tuple(mission.inject('alienigena')['position'])
    summary = mission.run()
    assert alien not in mission.path and summary['collisions'] == 0 and summary['success']


# ------------------------------------------------------------ event bugs
@pytest.mark.parametrize('planet,mode,seed', [('Marte', 'rover', 3), ('Marte', 'rover', 16),
                                              ('Júpiter', 'sonda', 9), ('Júpiter', 'sonda', 18)])
def test_low_battery_event_returns_to_a_reachable_refuge(planet, mode, seed):
    mission = HybridMission(planet=planet, mode=mode, seed=seed).prepare()
    for _ in range(8):
        mission.step()
    mission.inject('bateria_baja')
    summary = mission.run()
    assert summary['outcome'] != 'Sin solución: no existe ruta factible'
    assert summary['state'] in ('EXITO', 'MODO_SEGURO') and summary['battery_left'] >= 0


def test_critical_damage_ends_the_mission_in_safe_mode():
    mission = HybridMission(seed=42).prepare()
    for _ in range(6):
        mission.step()
    for _ in range(4):
        mission.inject('corrosion')
    summary = mission.run()
    assert summary['state'] == 'MODO_SEGURO' and summary['steps'] <= 8
    assert mission.logger.trace[-1]['reason'] == 'R03_DANO_CRITICO'


def test_wind_in_probe_mode_is_not_reported_as_a_quake():
    probe = HybridMission(planet='Júpiter', mode='sonda', seed=42).prepare()
    probe.step()
    probe.inject('viento')
    record = probe.step()
    assert record['reason'] == 'R16_ESPERA_VIENTO' and record['moved'] == []
    assert probe.wait_steps == 0
    assert probe.step()['reason'] != 'R16_ESPERA_VIENTO'
    rover = HybridMission(seed=42).prepare()
    rover.step()
    rover.inject('viento')
    assert rover.step()['moved']


def test_link_sensor_recovers_after_the_outage():
    mission = HybridMission(seed=42).prepare()
    mission.step()
    mission.inject('perdida_enlace')
    assert mission.step()['sensors']['link_available'] is False
    for _ in range(12):
        record = mission.step()
    assert record['sensors']['link_available'] is True


def test_clearing_a_cliff_restores_the_terrain():
    session = Session(seed=42)
    session.dispatch('step', {'n': 2})
    mission = session.mission
    cell = tuple(session.dispatch('inject', {'kind': 'barranco'})['map']['events'][-1]['position'])
    before = float(mission.belief.elevation[cell])
    session.dispatch('place', {'position': list(cell), 'kind': 'limpiar'})
    assert cell not in mission.world.cliffs
    assert abs(float(mission.world.elevation[cell]) - before) < 1e-6
    assert mission.step()['reason'] != 'R04_VETO_BARRANCO_CONFIRMADO'
