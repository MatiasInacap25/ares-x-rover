import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from ares import PlanetProfile, World, SensorSuite, Mission


def test_empty_battery():
    mission = Mission(World(seed=3), battery=0)
    start = mission.position
    for _ in range(3):
        mission.step((0, 1))
    assert mission.position == start
    assert mission.battery == 0
    assert mission.state.value == 'FRACASO'


@pytest.mark.parametrize('distance', [float('nan'), float('inf'), -float('inf'), 0, None])
def test_invalid_distance(distance):
    assert not SensorSuite.validate({'distance': distance})


def test_new_cliff_stops():
    mission = Mission(World(seed=2))
    mission.inject_event('barranco', position=(0, 1))
    mission.step((0, 1))
    assert mission.position == (0, 0)
    assert mission.state.value == 'REPLANIFICACION'
    assert (0, 1) in mission.world.cliffs


def test_seed_trace():
    def run():
        mission = Mission(World(seed=42))
        for target in [(0, 1), (1, 0), (0, 0)]:
            mission.step(target)
        return mission.logger.trace
    assert run() == run()


def test_jupiter_wheels():
    with pytest.raises(ValueError, match='sonda'):
        PlanetProfile.for_body('Júpiter', mode='ruedas')


def test_no_science():
    mission = Mission(World(seed=4, science_count=0))
    assert mission.science_progress == 1.0
    mission.step()
    assert mission.state.value == 'EXITO'


@pytest.mark.parametrize('body', ['Mercurio', 'Venus', 'Tierra', 'Marte', 'Júpiter', 'Saturno', 'Urano', 'Neptuno'])
def test_planet_modes(body):
    assert PlanetProfile.for_body(body, mode='sonda').mode == 'probe'
    if body in ['Júpiter', 'Saturno', 'Urano', 'Neptuno']:
        with pytest.raises(ValueError, match='suelo sólido'):
            PlanetProfile.for_body(body)
    else:
        assert PlanetProfile.for_body(body).rocky


def test_map_generation_and_manual_obstacle():
    import numpy as np
    a, b = World(seed=19), World(seed=19)
    assert (a.height, a.width) == (12, 16)
    assert np.array_equal(a.elevation, b.elevation)
    assert a.science_sites == b.science_sites
    assert not (a.obstacles & a.science_sites)
    a.add_obstacle((1, 1))
    assert not a.traversable((1, 1))
    with pytest.raises(ValueError):
        a.add_obstacle((-1, 0))


@pytest.mark.parametrize('failure', ['nan', 'saturation', 'missing'])
def test_sensor_failure_stops_and_logs(failure):
    mission = Mission(World(seed=3))
    mission.world.obstacles.discard((0, 1))
    mission.inject_event('falla_sensor', failure=failure)
    row = mission.step((0, 1))
    assert mission.position == (0, 0)
    assert row['state'] == 'MODO_SEGURO'
    assert row['sensors']['distance'] is None


def test_link_loss_local_operation_and_csv():
    import csv
    import io
    mission = Mission(World(seed=3))
    mission.world.obstacles.discard((0, 1))
    mission.inject_event('perdida_enlace')
    row = mission.step((0, 1))
    assert mission.position == (0, 1)
    assert not row['sensors']['link_available']
    rows = list(csv.DictReader(io.StringIO(mission.logger.export_csv())))
    assert len(rows) == 1
    assert rows[0]['action'] == 'avanzar'
    row['battery'] = -100
    assert mission.logger.trace[0]['battery'] >= 0


def test_events_and_narrative():
    from ares import EVENTS
    mission = Mission(World(seed=5), profile=PlanetProfile.for_body('Júpiter', 'probe'))
    for kind in EVENTS:
        mission.inject_event(kind, position=(1, 1))
    assert len(mission.pending_events) == len(EVENTS)
    assert mission.world.cliffs == {(1, 1)}
    assert mission.health == 80
    assert not mission.daylight
    assert mission.visibility == .2
    assert 'no confirma vida' in next(e['message'] for e in mission.pending_events if e['kind'] == 'biosenal_anomala')
    assert 'ficticio' in next(e['message'] for e in mission.pending_events if e['kind'] == 'alienigena')


def test_invalid_configuration():
    for kwargs in [{'battery': float('nan')}, {'battery': -1}, {'step_duration': 0}]:
        with pytest.raises(ValueError):
            Mission(World(), **kwargs)
    for kwargs in [{'width': 0}, {'difficulty': 'impossible'}, {'science_count': -1}]:
        with pytest.raises(ValueError):
            World(**kwargs)


def test_cliff_altimetry_and_insufficient_energy():
    mission = Mission(World(seed=1), battery=.5)
    mission.world.obstacles.discard((0, 1))
    mission.world.elevation[0, 1] = mission.world.elevation[0, 0] - 10
    assert mission.step((0, 1))['reason'] == 'BARRANCO_CONFIRMADO'
    mission.world.cliffs.clear()
    mission.world.elevation[0, 1] = 0
    assert mission.step((0, 1))['reason'] == 'ENERGIA_INSUFICIENTE'
    assert mission.battery == .5


def test_navigation_invalid_altimetry():
    mission = Mission(World(seed=1))
    mission.world.obstacles.discard((0, 1))
    mission.inject_event('falla_sensor', sensor='elevation_delta')
    assert mission.step((0, 1))['state'] == 'MODO_SEGURO'
    assert mission.position == (0, 0)


def test_thermal_limit():
    mission = Mission(World(seed=1), profile=PlanetProfile.for_body('Venus'), thermal_limit=100)
    assert mission.step()['reason'] == 'LIMITE_TERMICO'


@pytest.mark.parametrize('body', ['Júpiter', 'Saturno', 'Urano', 'Neptuno'])
def test_all_giants_require_probe(body):
    with pytest.raises(ValueError, match='suelo sólido.*sonda'):
        PlanetProfile.for_body(body, 'ruedas')
    assert PlanetProfile.for_body(body, 'sonda').mode == 'probe'


def test_invalid_altimeter_stops_before_movement():
    world = World(seed=1)
    world.obstacles.clear()
    sensors = SensorSuite(noise=0)
    sensors.fail('elevation_delta', 'nan')
    mission = Mission(world, sensors=sensors)
    row = mission.step((0, 1))
    assert row['action'] == 'detener'
    assert mission.position == (0, 0)
    assert row['state'] == 'MODO_SEGURO'


def test_empty_mission_does_not_override_cliff_stop():
    mission = Mission(World(science_count=0))
    mission.inject_event('barranco', position=(0, 1))
    assert mission.step((0, 1))['state'] == 'REPLANIFICACION'


def test_low_energy_allows_reachable_return():
    world = World(seed=0)
    world.obstacles.clear()
    mission = Mission(world, battery=5)
    mission.position = (0, 1)
    row = mission.step((0, 0))
    assert row['action'] == 'avanzar'
    assert mission.position == (0, 0)
    assert mission.battery == 4


def test_dust_reduces_solar_power():
    mission = Mission(World())
    before = mission.step()['sensors']['solar_power']
    mission.inject_event('tormenta_polvo')
    assert mission.step()['sensors']['solar_power'] < before


def test_invalid_target_is_safe():
    mission = Mission(World())
    row = mission.step((float('nan'), 1))
    assert row['action'] == 'detener'
    assert row['state'] == 'REPLANIFICACION'


def test_csv_and_snapshots():
    import csv
    import io
    from ares import MissionLogger
    logger = MissionLogger()
    readings = {'distance': float('nan')}
    row = logger.record(sensors=readings, reason='ESPERA')
    readings['distance'] = 10
    row['reason'] = 'changed'
    assert logger.trace[0]['sensors']['distance'] is None
    assert list(csv.DictReader(io.StringIO(logger.export_csv())))[0]['reason'] == 'ESPERA'


def test_energy_threshold_preserves_reachable_return():
    world = World(width=30, height=1)
    world.obstacles.clear()
    world.elevation[:] = 0
    mission = Mission(world, battery=20)
    for column in range(1, 11):
        mission.step((0, column))
    assert mission.battery == 10
    row = mission.step((0, 11))
    assert row['action'] == 'detener'
    assert mission.position == (0, 10)
    assert mission.battery == 10
    assert mission.step((0, 9))['action'] == 'avanzar'
