"""Real mission controls -> Mamdani payload and panel E browser checks.

Verification only: failures document defects; application code is not patched.
Run: .venv/bin/python -m pytest tests/test_panel_c_fuzzy.py -q
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


def assert_fuzzy(session, snapshot):
    f = snapshot['fuzzy']
    assert (f is not None) == POLICIES[snapshot['config']['policy']]['fuzzy']
    if f is None:
        return
    assert f['speed'] == f['centroid']
    assert f['caution'] == pytest.approx(1 - f['speed'], abs=.0001)
    assert len(f['curve']) == 51 and all(0 <= v <= 1 for v in f['curve'])
    assert len(f['all_rules']) == 12
    active = {r['id']: r['strength'] for r in f['rules']}
    for rule in f['all_rules']:
        strength = min(f['degrees'][var][label] for var, label in rule['antecedents'])
        assert active.get(rule['id'], 0) == pytest.approx(strength, abs=.001)
    manual = command(session, 'fuzzy_eval', **f['inputs'])
    assert manual['reason'] == f['reason']
    assert manual['speed'] == pytest.approx(f['speed'], abs=.003)


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
def test_configuration_resets_fuzzy_then_uses_selected_policy(config):
    s = Session(seed=42)
    before = command(s, 'step', n=1)
    reset = command(s, 'configure', **config)
    assert reset['fuzzy'] is None and reset['status']['step'] == 0
    for key, value in config.items():
        assert reset['config'][key] == value
    after = command(s, 'step', n=1)
    assert_fuzzy(s, after)
    if after['fuzzy']:
        assert after['fuzzy']['all_rules'] == before['fuzzy']['all_rules']


@pytest.mark.parametrize('kind', list(EVENT_LABELS) + ['navigation_total'])
def test_events_update_fuzzy_on_next_step_not_injection(kind):
    s = Session(seed=42)
    before = command(s, 'step', n=1)
    args = {'kind': kind} if kind != 'navigation_total' else {'kind': 'falla_sensor', 'sensor': 'todos'}
    injected = command(s, 'inject', **args)
    assert injected['fuzzy'] == before['fuzzy']
    assert injected['event_feed']['total'] == before['event_feed']['total'] + 1
    after = command(s, 'step', n=1)
    assert_fuzzy(s, after)
    f = after['fuzzy']
    if kind == 'bateria_baja':
        assert f['inputs']['battery'] < before['fuzzy']['inputs']['battery']
    if kind == 'ola_calor':
        assert f['inputs']['temperature'] > before['fuzzy']['inputs']['temperature']
    if kind == 'navigation_total':
        assert f['inputs']['distance'] == 2


@pytest.mark.parametrize('action,args', [('reset', {}), ('ghosts', {'enabled': True}),
                                      ('ghosts', {'enabled': False})])
def test_restart_controls_clear_fuzzy_and_reproduce_first_inference(action, args):
    s = Session(seed=42)
    before = command(s, 'step', n=1)
    assert command(s, action, **args)['fuzzy'] is None
    assert command(s, 'step', n=1)['fuzzy'] == before['fuzzy']


@pytest.mark.parametrize('kind', ['obstaculo', 'barranco', 'limpiar'])
def test_terrain_and_destination_actions_do_not_recompute_until_step(kind):
    s = Session(seed=42)
    before = command(s, 'step', n=1)
    cell = before['rna']['cell']
    for action, args in [('destination', {'position': cell}),
                         ('destination', {'position': cell}),
                         ('destination', {'position': cell}), ('destination', {}),
                         ('place', {'position': cell, 'kind': kind})]:
        assert command(s, action, **args)['fuzzy'] == before['fuzzy']
    assert_fuzzy(s, command(s, 'step', n=1))


@pytest.mark.parametrize('format', ['csv', 'json', 'comparison_csv'])
def test_exports_preserve_fuzzy_and_mission_state(format):
    s = Session(seed=42)
    before = command(s, 'step', n=1)
    result = s.dispatch('export', {'format': format})
    assert ('error' in result) == (format == 'comparison_csv')
    assert command(s, 'state') == before


def test_zero_battery_input_activates_critical_battery_rule():
    f = command(Session(), 'fuzzy_eval', distance=20, battery=0, slope=45, temperature=20)
    assert f['reason'] == 'INFERENCIA_MAMDANI'
    assert any(r['id'] == 2 and r['strength'] == 1 for r in f['rules'])
    assert 0 < f['speed'] < 1


@pytest.fixture(scope='module')
def browser_results(tmp_path_factory):
    if not (ROOT / 'server.py').exists():
        pytest.skip('server.py and the browser script are not bundled in the notebook')
    assert shutil.which('chromium') and shutil.which('node'), 'Chromium and Node are required'
    scratch = tmp_path_factory.mktemp('panel-c-e')
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
            port_file = scratch / 'profile' / 'DevToolsActivePort'
            wait_for(port_file.exists, chrome, 20)
            run = subprocess.run(['node', str(ROOT / 'tests/panel_c_fuzzy_browser.mjs'),
                port_file.read_text().splitlines()[0], str(app_port)],
                capture_output=True, text=True, timeout=180)
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


def test_panel_c_to_e_real_browser(browser_results):
    failures = [r for r in browser_results if not r['passed']]
    assert not failures, json.dumps(failures, ensure_ascii=False, indent=2)
