"""Mission panel C -> genetic planner F using the real public engine API.

Verification only. Run: .venv/bin/python -m pytest tests/test_panel_c_genetic.py -q
Browser checks require Chromium and Node with built-in WebSocket.
"""
import json
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


def assert_planner(session, snapshot):
    ga, runs = snapshot['ga'], snapshot['ga_runs']
    if not POLICIES[snapshot['config']['policy']]['ga']:
        assert ga['mode'] == 'voraz' and not runs and not ga['candidates']
        assert 'error' in session.dispatch('ga_generation', {'generation': 0})
        return
    assert runs and ga['mode'] in ('ag', 'retorno')
    for index, run in enumerate(runs):
        assert run['index'] == index and run['reason']
    if ga['mode'] == 'ag':
        assert ga['history'] and ga['generations_run'] == len(ga['history']) - 1
        if ga['chosen'] is not None:
            chosen = next(c for c in ga['candidates'] if c['index'] == ga['chosen'])
            assert chosen['feasible']
            assert not any(r['index'] == ga['chosen'] for r in ga['rejected'])
        for candidate in ga['candidates']:
            assert set(candidate['components']) == {'science', 'distance', 'energy', 'predicted_risk', 'time'}
        for route in snapshot['map']['candidates']:
            assert all(abs(a[0]-b[0])+abs(a[1]-b[1]) == 1 for a, b in zip(route, route[1:]))
            assert not {tuple(c) for c in route} & {tuple(c) for c in snapshot['map']['obstacles']}
    latest = command(session, 'ga_run', run=len(runs)-1)
    generation = command(session, 'ga_generation', run=len(runs)-1, generation=5)
    assert latest['run'] == generation['run'] == len(runs)-1
    assert generation['rows'] and generation['total'] == len(latest['ga']['history'])
    assert all({'chromosome', 'fitness', 'feasible', 'violations', 'components'} <= row.keys()
               for row in generation['rows'])


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
def test_configuration_prepares_new_plan_before_first_step(config):
    s = Session(seed=42)
    command(s, 'step', n=1)
    applied = command(s, 'configure', **config)
    assert applied['status']['step'] == 0
    for key, value in config.items():
        assert applied['config'][key] == value
    assert_planner(s, applied)
    if POLICIES[applied['config']['policy']]['ga']:
        assert len(applied['ga_runs']) == 1 and applied['ga_runs'][0]['step'] == 0


@pytest.mark.parametrize('kind', list(EVENT_LABELS) + ['navigation_total'])
def test_events_preserve_inspectable_plans_and_replan_when_required(kind):
    s = Session(seed=42)
    before = command(s, 'state')
    args = {'kind': kind} if kind != 'navigation_total' else {'kind': 'falla_sensor', 'sensor': 'todos'}
    injected = command(s, 'inject', **args)
    assert injected['event_feed']['total'] == before['event_feed']['total'] + 1
    if kind in ('meteorito', 'sismo', 'viento', 'bateria_baja', 'ola_calor', 'tormenta_polvo'):
        assert (len(injected['ga_runs']) > len(before['ga_runs'])
                or injected['ga']['mode'] == 'retorno')
    assert_planner(s, injected)
    assert_planner(s, command(s, 'step', n=1))


@pytest.mark.parametrize('action,args', [('reset', {}), ('ghosts', {'enabled': True}),
                                      ('ghosts', {'enabled': False})])
def test_restart_replaces_history_with_seeded_initial_plan(action, args):
    s = Session(seed=42)
    before = command(s, 'state')
    command(s, 'inject', kind='tormenta_polvo')
    reset = command(s, action, **args)
    assert reset['ga'] == before['ga'] and reset['ga_runs'] == before['ga_runs']


def test_in_place_drone_toggle_preserves_plan_and_execution_history():
    s = Session(seed=42)
    before = command(s, 'step', n=1)
    for enabled in (True, False):
        toggled = command(s, 'drone', enabled=enabled)
        assert toggled['config']['drone'] is enabled
        assert toggled['status']['step'] == before['status']['step']
        assert toggled['map']['path'] == before['map']['path']
        assert toggled['ga'] == before['ga'] and toggled['ga_runs'] == before['ga_runs']
        before = command(s, 'step', n=1)
        assert_planner(s, before)


@pytest.mark.parametrize('kind', ['obstaculo', 'barranco', 'limpiar'])
def test_destinations_and_terrain_preserve_public_generation_inspection(kind):
    s = Session(seed=42)
    before = command(s, 'state')
    cell = before['map']['route'][2]
    for action, args in [('destination', {'position': cell}), ('destination', {'position': cell}),
                         ('destination', {'position': cell}), ('destination', {}),
                         ('place', {'position': cell, 'kind': kind})]:
        assert_planner(s, command(s, action, **args))
    assert_planner(s, command(s, 'step', n=1))


@pytest.mark.parametrize('format', ['csv', 'json', 'comparison_csv'])
def test_exports_do_not_change_plans_or_execution_history(format):
    s = Session(seed=42)
    before = command(s, 'state')
    result = s.dispatch('export', {'format': format})
    assert ('error' in result) == (format == 'comparison_csv')
    assert command(s, 'state') == before


def test_generation_inspection_does_not_change_state_or_next_seeded_step():
    first, second = Session(seed=42), Session(seed=42)
    before = command(first, 'state')
    for generation in (0, 5, 999):
        command(first, 'ga_generation', run=0, generation=generation)
        command(first, 'ga_run', run=0)
    assert command(first, 'state') == before
    a, b = command(first, 'step', n=1), command(second, 'step', n=1)
    assert a['ga'] == b['ga'] and a['map'] == b['map']


def test_historical_generation_keeps_original_rows_after_mission_progress():
    s = Session(seed=42)
    before = command(s, 'ga_generation', run=0, generation=5)
    command(s, 'step', n=20)
    after = command(s, 'ga_generation', run=0, generation=5)
    assert after['rows'] == before['rows']
    assert after['best'] == before['best']


@pytest.fixture(scope='module')
def browser_results(tmp_path_factory):
    if not (ROOT / 'server.py').exists():
        pytest.skip('server.py and the browser script are not bundled in the notebook')
    assert shutil.which('chromium') and shutil.which('node'), 'Chromium and Node are required'
    scratch = tmp_path_factory.mktemp('panel-c-f')
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
            run = subprocess.run(['node', str(ROOT / 'tests/panel_c_genetic_browser.mjs'),
                port_file.read_text().splitlines()[0], str(app_port)], capture_output=True, text=True, timeout=240)
            assert run.returncode == 0, run.stderr + run.stdout
            (scratch / 'browser-results.json').write_text(run.stdout)
            return json.loads(run.stdout)
        finally:
            for process in reversed(processes):
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


def test_panel_c_to_f_real_browser(browser_results):
    failures = [r for r in browser_results if not r['passed']]
    assert not failures, json.dumps(failures, ensure_ascii=False, indent=2)
