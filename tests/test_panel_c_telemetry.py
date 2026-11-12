"""Real mission controls -> telemetry API and panel A rendering.

Verification only. Run: .venv/bin/python -m pytest tests/test_panel_c_telemetry.py -q
Chromium and Node with built-in WebSocket are required for the browser test.
"""
import json
import math
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from ares.api import Session  # noqa: E402
from ares.mission import EVENT_LABELS, POLICIES  # noqa: E402
from ares.planet import PROFILES  # noqa: E402


def command(session, name, **args):
    result = session.dispatch(name, args)
    assert 'error' not in result, result
    return result


def assert_readings(snapshot):
    t, st, planet = snapshot['telemetry'], snapshot['status'], snapshot['planet']
    assert 0 <= st['battery'] <= 100 and 0 <= st['health'] <= 100
    for key in ('distance', 'elevation_delta', 'slope', 'temperature_external',
                'radiation', 'pressure', 'oxygen_ambient', 'oxygen_stored', 'solar_power'):
        assert t[key] is None or math.isfinite(t[key]), (key, t[key])
    assert t['pressure'] == pytest.approx(planet['pressure'])
    assert t['oxygen_ambient'] == pytest.approx(planet['oxygen'])
    assert t['solar_power'] >= 0
    assert set(t['nav_valid']) == {'proximidad', 'lidar'}


CONFIGS = [
    *[{'planet': p[0], 'mode': 'rover' if p[1] else 'sonda'} for p in PROFILES.values()],
    {'mode': 'sonda'}, *[{'policy': p} for p in POLICIES],
    *[{'seed': s} for s in (0, 7, 42)],
    *[{'difficulty': d} for d in ('low', 'medium', 'high')],
    *[{'battery': b} for b in (0, 10, 50, 100)],
    *[{'step_duration': d} for d in (.5, 1, 1.5, 2, 2.5, 3)],
    {'drone': True}, {'drone': False},
]


@pytest.mark.parametrize('config', CONFIGS, ids=str)
def test_configuration_resets_readings_then_samples_selected_environment(config):
    s = Session(seed=42)
    command(s, 'step', n=1)
    applied = command(s, 'configure', **config)
    assert applied['status']['step'] == 0
    assert applied['status']['battery'] == applied['config']['battery']
    assert applied['status']['events_total'] == 0
    assert applied['telemetry']['distance'] is None
    assert applied['telemetry']['pressure'] is None
    for key, value in config.items():
        assert applied['config'][key] == value
    assert_readings(command(s, 'step', n=1))


@pytest.mark.parametrize('kind', list(EVENT_LABELS) + ['navigation_total'])
def test_events_update_current_status_and_sample_readings_on_next_step(kind):
    s = Session(seed=42)
    before = command(s, 'step', n=1)
    args = {'kind': kind} if kind != 'navigation_total' else {'kind': 'falla_sensor', 'sensor': 'todos'}
    injected = command(s, 'inject', **args)
    assert injected['telemetry'] == before['telemetry']
    assert injected['status']['events_total'] == before['status']['events_total'] + 1
    st, old = injected['status'], before['status']
    if kind == 'bateria_baja':
        assert st['battery'] == min(old['battery'], 10)
    if kind == 'corrosion':
        assert st['health'] == pytest.approx(old['health'] - 20)
    if kind == 'sismo':
        assert st['health'] == pytest.approx(old['health'] - 3) and st['vibration'] > 0
    if kind == 'ola_calor':
        assert st['temperature_internal'] == pytest.approx(old['temperature_internal'] + 35)
    if kind == 'tormenta_polvo':
        assert st['visibility'] == .2 and st['storm'] > 0
    if kind in ('dia', 'noche'):
        assert st['daylight'] is (kind == 'dia')
    if kind == 'perdida_enlace':
        assert not st['link']
    if kind == 'biosenal_anomala':
        assert st['anomalies'] == old['anomalies'] + 1
    if kind == 'alienigena':
        assert st['contacts'] == old['contacts'] + 1
    after = command(s, 'step', n=1)
    assert_readings(after)
    if kind in ('falla_sensor', 'navigation_total'):
        assert after['telemetry']['nav_valid']['proximidad'] is False
        assert after['telemetry']['distance'] is None
    if kind == 'navigation_total':
        assert after['telemetry']['nav_valid']['lidar'] is False


@pytest.mark.parametrize('action,args', [('reset', {}), ('ghosts', {'enabled': True}),
                                      ('ghosts', {'enabled': False})])
def test_restart_controls_clear_measurements_and_main_rover_counters(action, args):
    s = Session(seed=42)
    command(s, 'step', n=2)
    command(s, 'inject', kind='corrosion')
    reset = command(s, action, **args)
    assert reset['status']['step'] == reset['status']['events_total'] == 0
    assert reset['status']['health'] == 100
    assert reset['telemetry']['temperature_external'] is None
    assert_readings(command(s, 'step', n=1))


def test_drone_toggle_preserves_measurements_and_mission_progress():
    s = Session(seed=42)
    before = command(s, 'step', n=1)
    for enabled in (True, False):
        toggled = command(s, 'drone', enabled=enabled)
        assert toggled['telemetry'] == before['telemetry']
        assert toggled['status']['step'] == before['status']['step']
        assert bool(toggled['drone']) is enabled
        before = command(s, 'step', n=1)
        assert_readings(before)


@pytest.mark.parametrize('duration', [.5, 1, 1.5, 2, 2.5, 3])
def test_step_duration_updates_elapsed_time_and_disconnected_link_latency(duration):
    s = Session(seed=42, step_duration=duration)
    command(s, 'inject', kind='perdida_enlace')
    after = command(s, 'step', n=2)
    assert after['status']['t'] == pytest.approx(2 * duration)
    assert after['status']['link_latency'] == pytest.approx(2 * duration)


@pytest.mark.parametrize('format', ['csv', 'json', 'comparison_csv'])
def test_exports_do_not_mutate_telemetry(format):
    s = Session(seed=42)
    before = command(s, 'step', n=1)
    result = s.dispatch('export', {'format': format})
    assert ('error' in result) == (format == 'comparison_csv')
    assert command(s, 'state') == before


def test_same_seed_and_logical_steps_reproduce_telemetry():
    sessions = [Session(seed=42), Session(seed=42)]
    for operation, args in [('step', {'n': 1}), ('inject', {'kind': 'noche'}),
                            ('step', {'n': 2})]:
        a, b = [command(s, operation, **args) for s in sessions]
        assert a['telemetry'] == b['telemetry'] and a['status'] == b['status']


@pytest.fixture(scope='module')
def browser_results(tmp_path_factory):
    if not (ROOT / 'server.py').exists():
        pytest.skip('server.py and the browser script are not bundled in the notebook')
    assert shutil.which('chromium') and shutil.which('node'), 'Chromium and Node are required'
    scratch = tmp_path_factory.mktemp('panel-c-a')
    with socket.socket() as reservation:
        reservation.bind(('127.0.0.1', 0))
        app_port = reservation.getsockname()[1]
    processes = []
    with (scratch / 'server.log').open('w') as log:
        try:
            server = subprocess.Popen([sys.executable, str(ROOT / 'server.py'), '--port', str(app_port)],
                                      stdout=log, stderr=log, cwd=ROOT)
            processes.append(server)
            def wait_for(predicate, process, timeout):
                deadline = time.monotonic() + timeout
                while not predicate():
                    assert process.poll() is None, (scratch / 'server.log').read_text()
                    assert time.monotonic() < deadline, 'Process startup timed out'
                    time.sleep(.1)
            def listening():
                try:
                    urllib.request.urlopen(f'http://127.0.0.1:{app_port}/', timeout=1).close()
                    return True
                except OSError:
                    return False
            wait_for(listening, server, 90)
            chrome = subprocess.Popen(['chromium', '--headless', '--disable-gpu', '--no-first-run',
                '--no-default-browser-check', '--remote-debugging-port=0',
                f'--user-data-dir={scratch / "profile"}', 'about:blank'], stdout=log, stderr=log)
            processes.append(chrome)
            port_file = scratch / 'profile/DevToolsActivePort'
            wait_for(port_file.exists, chrome, 20)
            run = subprocess.run(['node', str(ROOT / 'tests/panel_c_telemetry_browser.mjs'),
                port_file.read_text().splitlines()[0], str(app_port)], capture_output=True, text=True, timeout=360)
            assert run.returncode == 0, run.stderr + run.stdout
            (scratch / 'browser-results.json').write_text(run.stdout)
            (scratch / 'browser-diagnostics.json').write_text(run.stderr)
            return json.loads(run.stdout)
        finally:
            for process in reversed(processes):
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


def test_panel_c_to_a_real_browser(browser_results):
    failures = [r for r in browser_results if not r['passed']]
    assert not failures, json.dumps(failures, ensure_ascii=False, indent=2)
